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
    # CTK-173 kinetic carousel: count-up cover (~3.7s) + 1 plain-reveal inner (~4.1s)
    # concatenated into one reel (~7.8s) via render_sequence + concat_clips.
    out = tmp_path / "f7.mp4"
    result = data_card.render_f7_arrivals(
        count=23, composition="all-restocks",
        items=[{"name": "WWC Sunkist Bounce Mushroom", "vendor": "WWC",
                "event_phrase": "back in stock", "fields": _fields("$250.00")}],
        now=NOW, out_path=out,
    )
    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out)
    assert 7.5 <= duration <= 8.1, f"expected ~7.8s (count-up cover + 1 reveal inner), got {duration}s"


@requires_chromium
def test_f9_lineage_carousel_render(tmp_path):
    # CTK-173 kinetic carousel: plain-staged-reveal cover (~3.8s) + 1 plain-reveal
    # inner (~4.1s) -> one reel (~7.9s).
    out = tmp_path / "f9.mp4"
    result = data_card.render_f9_lineage(
        coral="WWC Sunkist Bounce", vendor_count=2,
        items=[{"name": "WWC Sunkist Bounce Mushroom", "vendor": "TSA", "fields": _fields("$230.00")}],
        now=NOW, out_path=out,
    )
    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out)
    assert 7.6 <= duration <= 8.2, f"expected ~7.9s (reveal cover + 1 reveal inner), got {duration}s"


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


# --- CTK-173: F7/F9 kinetic carousel — held-frame INV-01 parity + concat join -----


def _held_and_frame0(html_doc, total, *, text_selector, reveal_all=None):
    """One browser session driving the seek function. Returns
    (held_text, f0_opacities, held_opacities):
      - held_text       — text_selector.textContent at the HELD/terminal frame
                          (total-1); the INV-01 / cover-stat parity surface (the
                          reveal toggles opacity/clip only, never the text).
      - f0_opacities    — computed opacity of every reveal_all match at frame 0
      - held_opacities  — computed opacity of every reveal_all match at the held frame
    The opacity pair is the held-frame VISIBILITY guard: a text-only assert passes
    even if a broken reveal schedule left the held frame fully HIDDEN (a blank final
    frame — a Tier 1A regression), so we also assert the targets are hidden at frame 0
    and fully shown at the held end. reveal_all=None skips the opacity probe (the
    count-up cover has no opacity reveal targets — its visibility is the digit
    textContent + the movement-coverage in test_count_up_sample_render)."""
    from playwright.sync_api import sync_playwright
    f0 = held = None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
            page.set_content(html_doc, wait_until="networkidle")
            if reveal_all:
                page.evaluate("seekTo(0)")
                f0 = [float(o) for o in page.eval_on_selector_all(
                    reveal_all, "els => els.map(e => getComputedStyle(e).opacity)")]
            page.evaluate(f"seekTo({total - 1})")
            held_text = page.eval_on_selector(text_selector, "el => el.textContent")
            if reveal_all:
                held = [float(o) for o in page.eval_on_selector_all(
                    reveal_all, "els => els.map(e => getComputedStyle(e).opacity)")]
            return held_text, f0, held
        finally:
            browser.close()


@requires_chromium
def test_f7_inner_reveal_held_frame_inv01_parity():
    # INV-01 against the HELD frame of an F7 inner: the live .row textContent equals
    # format_data_row byte-for-byte (the new animated-drill-in tracking surface for F7).
    from scrapers.tools.data_card import build_inner_reveal, _lead_html
    from scrapers.tools.data_row import format_data_row
    fields = _fields("$250.00")
    html_doc, total = build_inner_reveal(
        lead_html=_lead_html("WWC Sunkist Bounce Mushroom", "WWC", "back in stock"),
        fields=fields, now=NOW,
    )
    held_text, f0, held = _held_and_frame0(
        html_doc, total, text_selector=".row", reveal_all=".lead, .row .lab, .row .val")
    assert held_text == format_data_row(fields, NOW)
    # Held-frame VISIBILITY (no blank final frame): every reveal target hidden at
    # frame 0, fully shown at the held end.
    assert f0 and all(o == 0.0 for o in f0), f"reveal targets not hidden at frame 0: {f0}"
    assert held and all(o == 1.0 for o in held), f"reveal targets not fully shown at held frame: {held}"


@requires_chromium
def test_f9_inner_reveal_held_frame_inv01_parity():
    # INV-01 against the HELD frame of an F9 inner (the new animated-drill-in surface
    # for F9). F9 inners are 'listed' events — plain reveal, never a strike.
    from scrapers.tools.data_card import build_inner_reveal, _lead_html
    from scrapers.tools.data_row import format_data_row
    fields = _fields("$230.00")
    html_doc, total = build_inner_reveal(
        lead_html=_lead_html("WWC Sunkist Bounce Mushroom", "TSA", "listed"),
        fields=fields, now=NOW,
    )
    held_text, f0, held = _held_and_frame0(
        html_doc, total, text_selector=".row", reveal_all=".lead, .row .lab, .row .val")
    assert held_text == format_data_row(fields, NOW)
    # Held-frame VISIBILITY: every reveal target hidden at frame 0, fully shown at held.
    assert f0 and all(o == 0.0 for o in f0), f"reveal targets not hidden at frame 0: {f0}"
    assert held and all(o == 1.0 for o in held), f"reveal targets not fully shown at held frame: {held}"


@requires_chromium
def test_f7_count_up_cover_held_frame_matches_static_stat():
    # Migrated cover-stat assertion: the F7 count-up cover's HELD frame .stat text ==
    # the old static cover stat ("{count} {composition copy}") byte-for-byte. The count
    # has climbed to its terminal value at the held frame.
    from scrapers.tools.data_card import build_count_up, f7_cover_stat_html, _F7_COVER_COPY
    from bs4 import BeautifulSoup
    html_doc, total = build_count_up(count=23, label=_F7_COVER_COPY["all-restocks"])
    static = BeautifulSoup(f7_cover_stat_html(23, "all-restocks"), "html.parser").get_text()
    assert static == "23 back in stock this week."
    # The count-up cover has no opacity reveal targets (the digit ticks via textContent,
    # always visible); visibility = the held digit + the movement-coverage in
    # test_count_up_sample_render. Text-only held-frame assert here.
    held_text, _, _ = _held_and_frame0(html_doc, total, text_selector=".stat")
    assert held_text == static


@requires_chromium
def test_f9_cover_reveal_held_frame_matches_static_stat():
    # Migrated cover-stat assertion: the F9 reveal cover's HELD frame .stat text ==
    # the locked 'carried at N' prose byte-for-byte (the "carried at" lock, untouched).
    from scrapers.tools.data_card import build_f9_cover_reveal, f9_cover_stat_html
    from bs4 import BeautifulSoup
    html_doc, total = build_f9_cover_reveal(coral="WWC Sunkist Bounce", vendor_count=4)
    static = BeautifulSoup(f9_cover_stat_html("WWC Sunkist Bounce", 4), "html.parser").get_text()
    assert static == "WWC Sunkist Bounce — carried at 4 vendors right now."
    held_text, f0, held = _held_and_frame0(
        html_doc, total, text_selector=".stat", reveal_all=".stat .seg")
    assert held_text == static
    # Held-frame VISIBILITY: all three prose segments hidden at frame 0, shown at held.
    assert f0 and all(o == 0.0 for o in f0), f"segments not hidden at frame 0: {f0}"
    assert held and all(o == 1.0 for o in held), f"segments not fully shown at held frame: {held}"


def _decode_clean(path) -> str:
    """Full-decode scan: ffmpeg -v error decodes every frame to null and prints ONLY
    decode errors to stderr. A corrupt concat seam (mismatched SPS/PPS — the -c copy
    failure mode) decodes wrong downstream of the join and surfaces here. Empty stderr
    == a clean, non-corrupt reel. ffmpeg is the bundled imageio-ffmpeg binary."""
    import subprocess
    import imageio_ffmpeg
    proc = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return proc.stderr.strip()


@requires_chromium
def test_cross_producer_concat_integration_clean_join(tmp_path):
    # CTK-173 close 2 / INV-06 THE GATE: the first REAL multi-clip concat_clips on
    # rendered cards — a count-up cover clip + a plain-reveal inner clip, both via
    # render_sequence (shared _encode_args), joined by concat_clips with -c copy. The
    # full-decode scan must report ZERO errors: a clean, non-corrupt cross-producer
    # join (vs test_video's synthetic-frame version — this exercises the real F7 path).
    out = tmp_path / "f7-concat.mp4"
    data_card.render_f7_arrivals(
        count=12, composition="all-arrivals",
        items=[{"name": "WWC Sunkist Bounce Mushroom", "vendor": "WWC",
                "event_phrase": "just listed", "fields": _fields("$250.00")}],
        now=NOW, out_path=out,
    )
    assert out.exists() and out.stat().st_size > 0
    errors = _decode_clean(out)
    assert errors == "", f"concat join is not decode-clean (corrupt seam?):\n{errors}"
    # Duration is the sum of the two clips (the join did not drop/duplicate frames).
    assert 7.5 <= video.probe_duration(out) <= 8.1
