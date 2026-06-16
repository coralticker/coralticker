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
        {"label": "Lineage", "value": "WWC · 2018"},
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
