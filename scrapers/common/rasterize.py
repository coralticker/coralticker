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
