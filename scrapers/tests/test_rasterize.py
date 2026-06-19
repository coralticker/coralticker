"""CTK-164 B-path — rasterize smoke + F8 end-to-end (rasterize -> encode).

Chromium-GATED, like test_video's ffmpeg path: these skip cleanly when the
Playwright Chromium browser isn't installed (`playwright install chromium`), so
CI without the browser cached stays green. ffmpeg is always present (bundled via
imageio-ffmpeg), so the end-to-end gate is Chromium-only.

  python -m pytest scrapers/tests/test_rasterize.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import pytest
from PIL import Image

from scrapers.common import rasterize, video
from scrapers.tools import data_card

NOW = datetime(2026, 6, 16, 18, 0, 0, tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _chromium_ok() -> bool:
    """True if a headless Chromium can launch — else the browser binary isn't
    installed and the gated tests skip."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 — any launch failure -> gate off
        return False


requires_chromium = pytest.mark.skipif(
    not _chromium_ok(), reason="Playwright Chromium not installed (playwright install chromium)"
)

_SMOKE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;width:1080px;height:1920px;background:#F5F1EA;}
.box{position:absolute;left:140px;top:800px;width:800px;height:300px;background:#1B5E20;}
</style></head><body><div class="box"></div></body></html>"""


@requires_chromium
def test_rasterize_dims_and_nonblank(tmp_path):
    out = tmp_path / "smoke.png"
    rasterize.rasterize_html(_SMOKE_HTML, out)
    assert out.exists()
    img = Image.open(out)
    assert img.size == (rasterize.FRAME_W, rasterize.FRAME_H)   # 1080x1920, scale 1
    # Non-blank: a cream canvas with a forest box has >1 distinct colour.
    lo, hi = img.convert("L").getextrema()
    assert lo != hi, "rasterized frame is a single flat colour (blank / font-swap race)"


@requires_chromium
def test_f8_end_to_end_render(tmp_path):
    # Full B-path chain on a single card: assemble F8 HTML -> rasterize -> encode.
    fields = [
        {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650", "newValue": "$455"}},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-16T12:00:00Z"}},
    ]
    out = tmp_path / "f8.mp4"
    result = data_card.render_f8_superlative(
        name="WWC Sunkist Bounce Mushroom", pct=30, fields=fields, now=NOW, out_path=out,
    )
    assert result.exists() and result.stat().st_size > 0

    # The intermediate frame is a real 1080x1920 PNG.
    png = tmp_path / "f8.png"
    assert png.exists()
    assert Image.open(png).size == (rasterize.FRAME_W, rasterize.FRAME_H)

    # DATA_CARD_MOTION duration (~7s) landed.
    duration = video.probe_duration(out)
    assert 6.5 <= duration <= 7.5, f"expected ~7s, got {duration}s"


def _fields(price_value):
    from scrapers.tools.content_queries import build_card_fields
    return build_card_fields(price_value=price_value, origin="WWC", year=None,
                             listed_at="2026-06-16T12:00:00Z")


@requires_chromium
def test_f7_arrivals_carousel_render(tmp_path):
    # Cover-rides-the-reel: cover + 1 inner -> one concatenated reel (~2*7s).
    out = tmp_path / "f7.mp4"
    result = data_card.render_f7_arrivals(
        count=23, composition="all-restocks",
        items=[{"name": "WWC Sunkist Bounce Mushroom", "vendor": "WWC",
                "event_phrase": "back in stock", "fields": _fields("$250.00")}],
        now=NOW, out_path=out,
    )
    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out)
    assert 13.0 <= duration <= 15.0, f"expected ~14s (cover + 1 inner), got {duration}s"


@requires_chromium
def test_f9_lineage_carousel_render(tmp_path):
    out = tmp_path / "f9.mp4"
    result = data_card.render_f9_lineage(
        coral="WWC Sunkist Bounce", vendor_count=2,
        items=[{"name": "WWC Sunkist Bounce Mushroom", "vendor": "TSA", "fields": _fields("$230.00")}],
        now=NOW, out_path=out,
    )
    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out)
    assert 13.0 <= duration <= 15.0, f"expected ~14s (cover + 1 inner), got {duration}s"


# --- PB-2: content-animation capture (rasterize_sequence) + count-up sample ---

# A seek-driven page: the body colour is a pure function of the frame index, so a
# correct frame-step yields a DIFFERENT image per i; a broken stepper (seek_fn never
# called) yields N identical frames — which the distinctness assert catches.
_SEEK_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;width:1080px;height:1920px;}</style></head><body>
<script>window.seekTo=function(i){document.body.style.background=
'rgb('+(i*40)+',40,40)';};window.seekTo(0);</script></body></html>"""


@requires_chromium
def test_rasterize_sequence_steps_per_frame(tmp_path):
    frames = rasterize.rasterize_sequence(_SEEK_HTML, 4, tmp_path / "seq")
    assert len(frames) == 4
    assert all(f.exists() for f in frames)
    # Each frame is seek-distinct — proves seekTo(i) drives the capture (not a
    # single repeated screenshot). Mean R channel rises with i.
    import hashlib
    hashes = {hashlib.md5(f.read_bytes()).hexdigest() for f in frames}
    assert len(hashes) == 4, "frames are not distinct — seek stepper not driving capture"


@requires_chromium
def test_count_up_sample_render(tmp_path):
    # End-to-end count-up: assemble card -> rasterize_sequence (build+hold) ->
    # render_sequence. v2 timing: 2.2s build + 1.5s hold = ~3.7s at 30fps.
    out = tmp_path / "count-up.mp4"
    result = data_card.render_count_up(count=758, out_path=out)
    assert result.exists() and result.stat().st_size > 0

    duration = video.probe_duration(out)
    assert 3.5 <= duration <= 3.9, f"expected ~3.7s (2.2s build + 1.5s hold), got {duration}s"

    # The PNG sequence: 66 build + 45 hold = 111 frames at 30fps.
    seq = sorted((tmp_path / "count-up-frames").glob("frame_*.png"))
    assert len(seq) == 111, f"expected 111 frames, got {len(seq)}"

    import hashlib
    def h(p): return hashlib.md5(p.read_bytes()).hexdigest()
    # The number MOVED (frame 0 != last build frame) — fails if seekTo never ticked.
    assert h(seq[0]) != h(seq[65]), "count did not move — easing/seek broken"
    # The hold is motionless: the terminal value is reached by the last build frame
    # and every frame from there to the end is identical (the terminal == N seam).
    assert len({h(seq[i]) for i in range(65, 111)}) == 1, "hold is not motionless / terminal seam jumps"


# --- reveal + strike-draw F8 drill-in (the INV-01-bound motion) ---------------

_REVEAL_FIELDS = [
    {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00"}},
    {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-15T18:00:00Z"}},
]


@requires_chromium
def test_f8_reveal_held_frame_inv01_parity(tmp_path):
    # THE INV-01 gate run against the HELD/TERMINAL frame, not just the static card:
    # load the card, seekTo(total-1), then read the LIVE .row textContent and assert
    # it equals format_data_row byte-for-byte. Proves the reveal/strike-draw animation
    # (opacity/clip/strike-width only) never mutates the row text at the held end.
    from scrapers.tools.data_card import build_f8_reveal
    from scrapers.tools.data_row import format_data_row
    from playwright.sync_api import sync_playwright

    html_doc, total = build_f8_reveal(name="WWC Sunkist Bounce Mushroom", pct=30,
                                      fields=_REVEAL_FIELDS, now=NOW)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
            page.set_content(html_doc, wait_until="networkidle")
            page.evaluate(f"seekTo({total - 1})")
            row_text = page.eval_on_selector(".row", "el => el.textContent")
        finally:
            browser.close()
    assert row_text == format_data_row(_REVEAL_FIELDS, NOW)


@requires_chromium
def test_f8_reveal_renders(tmp_path):
    # Plain-reveal F8 (count-up % variant dropped 2026-06-18). The extended un-struck
    # hold (0.85s) + slowed strike push the total to ~5.9s (4.4s build + 1.5s hold).
    from scrapers.tools.data_card import render_f8_reveal
    out = tmp_path / "f8-reveal.mp4"
    result = render_f8_reveal(name="WWC Sunkist Bounce Mushroom", pct=30,
                              fields=_REVEAL_FIELDS, now=NOW, out_path=out)
    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out)
    assert 5.6 <= duration <= 6.2, f"expected ~5.9s, got {duration}s"
