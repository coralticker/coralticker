"""CTK-164 B-path — the html->png rasterizer: the consumer-agnostic seam between
card HTML and the encode primitive (PB-1).

One job: take an HTML document, render it in Chromium at a fixed viewport, and
write the viewport as a PNG. It is **motion-blind and consumer-agnostic** — it
knows nothing about vendors, cards, listings, or data rows. The B-path data-card
pipeline (data_card.py) generates the HTML; this turns it into a frame; video.py's
render_kenburns animates the frame. CTK-163's data-viz path imports this same
function rather than forking its own (PB-1).

Chromium specifically (PB-6), not a lighter WebKit/Pillow path: the cards are IBM
Plex webfonts + flexbox + box-shadow authored against Blink; a lighter engine
risks font-metric drift that breaks the fidelity Pillow was rejected for. PB-4
neutralises the browser weight by isolating the render off the scraper-cron runs,
so there is no cost pressure to trade fidelity.

The page IS the frame: the card HTML sets <body> to the output dimensions, so a
plain viewport screenshot (no element clipping, no full_page stitching) captures
production 1:1. Webfonts load over the network — we wait for networkidle AND
document.fonts.ready so a screenshot never races the font swap (a FOUT frame is a
silent fidelity bug).

Browser binary: NOT pip-shipped. Install once with `playwright install chromium`
(local Mac render first per PB-4). A missing browser fails LOUD on first call
(playwright raises), never silently renders a blank or default-font frame.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

# Output canvas — IG Reels / vertical 9:16. The card HTML sizes <body> to match;
# kept local (not imported from video.py) so the rasterizer stays a standalone
# html->png primitive with no encode-layer dependency.
FRAME_W = 1080
FRAME_H = 1920

# Webfont settle budget after networkidle + fonts.ready, in ms. fonts.ready
# resolves when faces are loaded; this absorbs the paint after the swap.
_FONT_SETTLE_MS = 150


def rasterize_html(
    html: str,
    out_path: str | Path,
    *,
    width: int = FRAME_W,
    height: int = FRAME_H,
) -> Path:
    """Render an HTML string in Chromium at width x height and write the viewport
    to out_path as a PNG. Returns out_path.

    Consumer-agnostic: html is opaque markup, out_path is opaque. device_scale_
    factor is 1 so the PNG is exactly width x height device pixels (the encode
    primitive expects frames already at output dimensions).

    Raises loudly if Chromium is absent or the page errors — a blank/default-font
    frame is a worse failure than a crash."""
    out_path = Path(out_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            # networkidle waits for the Google Fonts CSS + woff2 fetches; fonts.ready
            # then guarantees the faces are applied before we paint.
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(_FONT_SETTLE_MS)
            page.screenshot(path=str(out_path), type="png")
        finally:
            browser.close()
    return out_path


def rasterize_sequence(
    html: str,
    frame_count: int,
    work_dir: str | Path,
    *,
    seek_fn: str = "seekTo",
    width: int = FRAME_W,
    height: int = FRAME_H,
) -> list[Path]:
    """Render an HTML document carrying a JS seek function as a PNG SEQUENCE. For
    each frame i in range(frame_count): call window.{seek_fn}(i) in the page to set
    the i-th content state, then screenshot. Returns the ordered list of PNG paths
    (frame_00000.png .. in work_dir).

    This is the capture seam for CONTENT animation (count-up, em-dash reveal,
    strike-draw — branding-guide §"IG data-card motion"): the card owns its
    animation as a pure function of an integer frame index, and this drives it
    frame-by-frame. Frames come from the seek function, NEVER wall-clock / CSS time
    (a time-driven capture races the screenshot cadence and is unreproducible) — so
    frame i is byte-identical on every run. video.py's render_sequence encodes the
    result; CTK-163's data-viz path reuses this same primitive (consumer-agnostic —
    html-with-a-seek-fn in, PNG sequence out, blind to count-ups / cards / vendors).

    document.fonts.ready + the settle wait happen ONCE before stepping (the webfonts
    are loaded for the whole sequence, not re-fetched per frame), so no frame races
    the font swap. Chromium absent, a page error, or a missing/throwing seek_fn
    fails LOUD (a blank or stuck-frame sequence is a worse, silent fidelity bug)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(_FONT_SETTLE_MS)
            for i in range(frame_count):
                page.evaluate(f"{seek_fn}({i})")
                out = work_dir / f"frame_{i:05d}.png"
                page.screenshot(path=str(out), type="png")
                paths.append(out)
        finally:
            browser.close()
    return paths
